#include <iostream>
#include <fstream>
#include <string>
#include <vector>
#include <algorithm>
#include <iomanip>
#include <cmath>
#include <set>
#include <map>

#include "Config.h"
#include "DataLoader.h"
#include "MILPBuilder.h"
#include "Highs.h"

std::string getCmdOption(char ** begin, char ** end, const std::string & option) {
    char ** itr = std::find(begin, end, option);
    if (itr != end && ++itr != end) return std::string(*itr);
    return "";
}

std::string getExchangeBaseName(const std::string& name) {
    size_t pos = name.find_first_of("([");
    if (pos != std::string::npos) {
        return name.substr(0, pos);
    }
    return name;
}

struct Contributor {
    std::string species_id;
    std::string rxn_name;
    double flux;
};

void writeSolutionJson(const std::string& path, const Highs& highs, const MILPBuilder::VarMap& vars, const ProblemData& data, const SolverConfig& config, double time) {
    const HighsInfo& info = highs.getInfo();
    const HighsModelStatus& status = highs.getModelStatus();

    bool statusOk = (status == HighsModelStatus::kOptimal ||
                     status == HighsModelStatus::kTimeLimit ||
                     status == HighsModelStatus::kIterationLimit);

    const HighsSolution& sol = highs.getSolution();
    // hasSolution is true only when HiGHS found a valid integer-feasible solution.
    // When time/iteration limit is hit with only an LP relaxation (no integer incumbent),
    // sol.col_value is non-empty but objective_function_value is +inf — which is not
    // valid JSON. Guard with isfinite() to treat that case as "no solution".
    bool hasSolution = statusOk &&
                       !sol.col_value.empty() &&
                       std::isfinite(info.objective_function_value);

    std::string statusStr = highs.modelStatusToString(status);

    // Helper: replace any non-finite double (nan/inf) with 0.0 before writing JSON.
    // Prevents malformed output when FBA reference values or solver internals are
    // infinite/undefined.
    auto safeD = [](double v) -> double {
        return std::isfinite(v) ? v : 0.0;
    };

    double total_biomass = 0.0;
    double total_scfa_prod = 0.0;
    std::vector<std::pair<std::string, double>> biomass_contributors;

    struct ScfaInfo {
        std::string full_comm_name;
        double comm_flux;
        std::vector<Contributor> contributors;
    };
    std::map<std::string, ScfaInfo> scfa_data_map;

    // Compute total species columns upfront (needed for target reaction name lookup)
    int total_species_cols = 0;
    for (const auto& v_k : vars.v) total_species_cols += v_k.size();

    // Build target reaction names from scfaIndices + commFluxMap
    std::vector<std::string> target_rxn_names;
    for (int global_idx : data.scfaIndices) {
        int comm_local_idx = (global_idx - 1) - total_species_cols;
        std::string mapKey = "EX_comm_" + std::to_string(comm_local_idx);
        std::string realName = data.commFluxMap.count(mapKey) ? data.commFluxMap.at(mapKey) : mapKey;
        target_rxn_names.push_back(realName);
    }

    if (hasSolution) {
        for (int k = 0; k < data.numSpecies; ++k) {
            int local_bio_idx = data.biomassIndices[k] - 1;

            if (local_bio_idx >= 0 && local_bio_idx < (int)vars.v[k].size()) {
                int global_col_idx = vars.v[k][local_bio_idx];

                if (global_col_idx >= 0 && global_col_idx < (int)sol.col_value.size()) {
                    double val = sol.col_value[global_col_idx];
                    total_biomass += val;

                    if (std::abs(val) > 1e-6) {
                        std::string sp_name = "org" + std::to_string(k + 1);
                        if (data.speciesMap.count(k)) sp_name = data.speciesMap.at(k);
                        biomass_contributors.push_back({sp_name, val});
                    }
                }
            }
        }

        for (int global_idx : data.scfaIndices) {
            int comm_local_idx = (global_idx - 1) - total_species_cols;
            if (comm_local_idx >= 0 && comm_local_idx < (int)vars.v_comm.size()) {
                double val = sol.col_value[vars.v_comm[comm_local_idx]];
                total_scfa_prod += val;

                std::string mapKey = "EX_comm_" + std::to_string(comm_local_idx);
                std::string realName = mapKey;
                if (data.commFluxMap.count(mapKey)) realName = data.commFluxMap.at(mapKey);

                std::string base = getExchangeBaseName(realName);
                scfa_data_map[base].full_comm_name = realName;
                scfa_data_map[base].comm_flux = val;
            }
        }

        for (int k = 0; k < data.numSpecies; ++k) {
            if (sol.col_value[vars.x[k]] < 0.5) continue;

            std::string sp_name = "org" + std::to_string(k + 1);
            if (data.speciesMap.count(k)) sp_name = data.speciesMap.at(k);

            bool hasNames = (k < (int)data.speciesRxnNames.size() && !data.speciesRxnNames[k].empty());

            for (size_t j = 0; j < vars.v[k].size(); ++j) {
                double val = sol.col_value[vars.v[k][j]];
                if (std::abs(val) < 1e-6) continue;

                std::string rName;
                if (hasNames && j < data.speciesRxnNames[k].size()) {
                    rName = data.speciesRxnNames[k][j];
                } else {
                    rName = "rxn_" + std::to_string(j);
                }

                if (rName.rfind("EX_", 0) != 0) continue;

                std::string base = getExchangeBaseName(rName);

                if (scfa_data_map.count(base)) {
                    scfa_data_map[base].contributors.push_back({sp_name, rName, val});
                }
            }
        }
    }

    std::ofstream out(path);
    out << std::fixed << std::setprecision(6);
    out << "{\n";
    out << "  \"status\": \"" << statusStr << "\",\n";
    out << "  \"phase\": \"simulation\",\n";
    out << "  \"objective_value\": " << safeD(hasSolution ? info.objective_function_value : 0.0) << ",\n";
    out << "  \"solve_time_sec\": " << safeD(time) << ",\n";

    out << "  \"configuration\": {\n";
    out << "    \"min_community_growth_threshold\": " << config.minCommunityGrowth << ",\n";
    out << "    \"target_production_threshold\": " << config.reactionProductionFloor << ",\n";
    out << "    \"min_species_count\": " << config.minSpeciesCount << ",\n";
    out << "    \"time_limit_sec\": " << config.timeLimit << "\n";
    out << "  },\n";

    out << "  \"reference_original_biomass\": " << safeD(data.refGrowthMax) << ",\n";
    out << "  \"reference_biomass_constraint\": " << safeD(config.minCommunityGrowth * data.refGrowthMax) << ",\n";

    bool hasRefScfa = std::isfinite(data.refScfaMax) && data.refScfaMax > 1e-12;
    out << "  \"reference_original_target\": " << safeD(hasRefScfa ? data.refScfaMax : 0.0) << ",\n";
    out << "  \"reference_target_constraint\": " << safeD(hasRefScfa ? config.reactionProductionFloor * data.refScfaMax : 0.0) << ",\n";
    out << "  \"reference_target_breakdown\": {\n";
    {
        auto bdit = data.refScfaBreakdown.begin();
        while (bdit != data.refScfaBreakdown.end()) {
            out << "    \"" << bdit->first << "\": " << safeD(bdit->second);
            if (++bdit != data.refScfaBreakdown.end()) out << ",";
            out << "\n";
        }
    }
    out << "  },\n";

    out << "  \"target_reactions\": [\n";
    for (size_t i = 0; i < target_rxn_names.size(); ++i) {
        out << "    \"" << target_rxn_names[i] << "\"";
        if (i + 1 < target_rxn_names.size()) out << ",";
        out << "\n";
    }
    out << "  ],\n";

    out << "  \"total_community_biomass\": " << safeD(total_biomass) << ",\n";
    out << "  \"biomass_breakdown\": [\n";
    for (size_t i = 0; i < biomass_contributors.size(); ++i) {
        out << "    { \"id\": \"" << biomass_contributors[i].first << "\", \"flux\": " << safeD(biomass_contributors[i].second) << " }";
        if (i < biomass_contributors.size() - 1) out << ",";
        out << "\n";
    }
    out << "  ],\n";

    out << "  \"total_target_production\": " << safeD(total_scfa_prod) << ",\n";
    out << "  \"target_breakdown\": {\n";
    auto it = scfa_data_map.begin();
    while (it != scfa_data_map.end()) {
        const auto& info = it->second;
        out << "    \"" << info.full_comm_name << "\": {\n";
        out << "      \"total_flux\": " << safeD(info.comm_flux) << ",\n";
        out << "      \"contributors\": [\n";
        for (size_t i = 0; i < info.contributors.size(); ++i) {
            const auto& c = info.contributors[i];
            out << "        { \"id\": \"" << c.species_id << "\", \"flux\": " << safeD(c.flux) << ", \"reaction\": \"" << c.rxn_name << "\" }";
            if (i < info.contributors.size() - 1) out << ",";
            out << "\n";
        }
        out << "      ]\n";
        out << "    }";
        if (++it != scfa_data_map.end()) out << ",";
        out << "\n";
    }
    out << "  },\n";

    out << "  \"detailed_composition\": [\n";
    if (hasSolution) {
        bool firstSp = true;
        for (int k = 0; k < data.numSpecies; ++k) {
            double abundance = sol.col_value[vars.x[k]];

            if (abundance > 0.5) {
                if (!firstSp) out << ",\n";
                firstSp = false;

                std::string name = "org" + std::to_string(k + 1);
                if (data.speciesMap.count(k)) name = data.speciesMap.at(k);

                double bio_flux = 0.0;
                int local_bio_idx = data.biomassIndices[k] - 1;

                if (local_bio_idx >= 0 && local_bio_idx < (int)vars.v[k].size()) {
                    int global_col_idx = vars.v[k][local_bio_idx];
                    if (global_col_idx >= 0 && global_col_idx < (int)sol.col_value.size()) {
                        bio_flux = sol.col_value[global_col_idx];
                    }
                }

                out << "    {\n";
                out << "      \"id\": \"" << name << "\",\n";
                out << "      \"abundance_binary\": " << safeD(abundance) << ",\n";
                out << "      \"biomass_flux\": " << safeD(bio_flux) << ",\n";
                out << "      \"metabolic_exchanges\": {\n";

                bool firstEx = true;
                bool hasNames = (k < (int)data.speciesRxnNames.size() && !data.speciesRxnNames[k].empty());

                for (size_t j = 0; j < vars.v[k].size(); ++j) {
                    double val = sol.col_value[vars.v[k][j]];

                    if (std::abs(val) > 1e-6) {
                        std::string rName;
                        if (hasNames && j < data.speciesRxnNames[k].size()) {
                            rName = data.speciesRxnNames[k][j];
                        } else {
                            rName = "rxn_" + std::to_string(j);
                        }

                        if (rName.rfind("EX_", 0) == 0) {
                            std::string cleanName = getExchangeBaseName(rName);
                            if (!firstEx) out << ",\n";
                            out << "        \"" << cleanName << "\": " << safeD(val);
                            firstEx = false;
                        }
                    }
                }
                out << "\n      },\n";

                out << "      \"internal_reactions\": {\n";
                bool firstInt = true;
                for (size_t j = 0; j < vars.v[k].size(); ++j) {
                    double val = sol.col_value[vars.v[k][j]];

                    if (std::abs(val) > 1e-6) {
                        std::string rName;
                        if (hasNames && j < data.speciesRxnNames[k].size()) {
                            rName = data.speciesRxnNames[k][j];
                        } else {
                            rName = "rxn_" + std::to_string(j);
                        }

                        if (rName.rfind("EX_", 0) != 0) {
                            if (!firstInt) out << ",\n";

                            std::string suffix = "_" + name;
                            std::string cleanKey = rName;

                            if (cleanKey.length() > suffix.length() &&
                                cleanKey.compare(cleanKey.length() - suffix.length(), suffix.length(), suffix) == 0) {
                                cleanKey = cleanKey.substr(0, cleanKey.length() - suffix.length());
                            }

                            out << "        \"" << cleanKey << "\": " << safeD(val);
                            firstInt = false;
                        }
                    }
                }
                out << "\n      }\n";
                out << "    }";
            }
        }
    }
    out << "\n  ],\n";

    out << "  \"community_fluxes\": {\n";
    if (hasSolution) {
        bool firstComm = true;
        for (size_t j = 0; j < vars.v_comm.size(); ++j) {
            double val = sol.col_value[vars.v_comm[j]];
            if (std::abs(val) > 1e-6) {
                if (!firstComm) out << ",\n";

                std::string mapKey = "EX_comm_" + std::to_string(j);
                std::string realName = mapKey;

                if (data.commFluxMap.count(mapKey)) {
                    realName = data.commFluxMap.at(mapKey);
                }

                out << "    \"" << realName << "\": " << safeD(val);
                firstComm = false;
            }
        }
    }
    out << "\n  }\n";

    out << "}\n";
    out.close();
}

int main(int argc, char** argv) {
    std::cout << "==========================================================" << std::endl;
    std::cout << "   MINeBUGS SOLVER - VERSION: v1.4 (SAFE JSON + TIMELIMIT FIX) " << std::endl;
    std::cout << "==========================================================" << std::endl;

    SolverConfig config;
    config.inputDir = getCmdOption(argv, argv + argc, "--input-dir");
    config.outputFile = getCmdOption(argv, argv + argc, "--output-file");

    std::string s_minGrowth = getCmdOption(argv, argv + argc, "--min-growth");
    if (!s_minGrowth.empty()) config.minCommunityGrowth = std::stod(s_minGrowth);

    std::string s_prodFloor = getCmdOption(argv, argv + argc, "--prod-floor");
    if (!s_prodFloor.empty()) config.reactionProductionFloor = std::stod(s_prodFloor);

    std::string s_timeLimit = getCmdOption(argv, argv + argc, "--time-limit");
    if (!s_timeLimit.empty()) config.timeLimit = std::stod(s_timeLimit);

    std::string s_minSpecies = getCmdOption(argv, argv + argc, "--min-species");
    if (!s_minSpecies.empty()) config.minSpeciesCount = std::stoi(s_minSpecies);

    if (config.inputDir.empty() || config.outputFile.empty()) {
        std::cerr << "Usage: ./solver_cpp --input-dir <dir> --output-file <file.json> [options]" << std::endl;
        return 1;
    }

    try {
        std::cout << "[MAIN] Initializing DataLoader..." << std::endl;
        DataLoader loader(config);
        ProblemData data = loader.loadMetadata();

        std::cout << "[MAIN] Building MILP Model..." << std::endl;
        MILPBuilder builder(config, data);
        HighsModel model = builder.build();

        Highs highs;
        highs.setOptionValue("time_limit", config.timeLimit);
        highs.setOptionValue("presolve", "on");

        std::cout << "[MAIN] Starting Solver..." << std::endl;
        HighsStatus return_status = highs.passModel(model);
        if (return_status != HighsStatus::kOk) throw std::runtime_error("Highs passModel failed");

        return_status = highs.run();

        std::string statusStr = highs.modelStatusToString(highs.getModelStatus());
        std::cout << "[MAIN] Solver finished. Status: " << statusStr << std::endl;

        writeSolutionJson(config.outputFile, highs, builder.getVars(), data, config, highs.getRunTime());

        std::cout << "[MAIN] Detailed report saved to: " << config.outputFile << std::endl;

    } catch (const std::exception& e) {
        std::cerr << "[ERROR] Exception: " << e.what() << std::endl;
        return 1;
    }

    return 0;
}