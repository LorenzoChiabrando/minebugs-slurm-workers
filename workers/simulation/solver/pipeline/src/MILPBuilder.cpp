#include "MILPBuilder.h"
#include "DataLoader.h"
#include <iostream>
#include <numeric>
#include <cmath>
#include <sstream>
#include <map>
#include <algorithm>

const double INF = kHighsInf;

MILPBuilder::MILPBuilder(const SolverConfig& config, const ProblemData& data)
    : config_(config), data_(data) {
    
    model_.lp_.num_col_ = 0;
    model_.lp_.num_row_ = 0;
    model_.lp_.offset_ = 0;
    model_.lp_.sense_ = ObjSense::kMinimize;
    model_.lp_.a_matrix_.format_ = MatrixFormat::kRowwise;
    model_.lp_.a_matrix_.start_ = {0};
}

HighsModel MILPBuilder::build() {
    std::cout << "[BUILDER] Starting model construction (Sparse Optimized)..." << std::endl;

    addSpeciesVariables();
    addFluxVariables();
    addObjectiveLinearizationVariable();


    addCommunityMassBalance();       
    addCouplingConstraints();        
    addInternalMassBalance();        
    
    addGrowthConstraint();           
    addFunctionConstraint();         
    addObjectiveConstraints();       
    addMinSpeciesConstraint();       

    std::cout << "[BUILDER] Model built successfully." << std::endl;
    std::cout << "          Rows: " << model_.lp_.num_row_ << std::endl;
    std::cout << "          Cols: " << model_.lp_.num_col_ << std::endl;
    std::cout << "          Nonzeros: " << model_.lp_.a_matrix_.value_.size() << std::endl;

    return model_;
}

// VARIABLES

void MILPBuilder::addSpeciesVariables() {
    for (int k = 0; k < data_.numSpecies; ++k) {
        vars_.x.push_back(model_.lp_.num_col_);
        model_.lp_.col_cost_.push_back(1.0);
        model_.lp_.col_lower_.push_back(0.0);
        model_.lp_.col_upper_.push_back(1.0);
        model_.lp_.integrality_.push_back(HighsVarType::kInteger);
        model_.lp_.num_col_++;
    }
}

void MILPBuilder::addFluxVariables() {
    vars_.v.resize(data_.numSpecies);

    for (int k = 0; k < data_.numSpecies; ++k) {
        std::stringstream ss_lb;
        ss_lb << "lower_upper_bounds/org" << (k + 1) << "_lower_bounds.txt";
        auto lbs = DataLoader::readVector(config_.inputDir + "/" + ss_lb.str());
        
        for (size_t j = 0; j < lbs.size(); ++j) {
            vars_.v[k].push_back(model_.lp_.num_col_);
            model_.lp_.col_cost_.push_back(0.0);

            model_.lp_.col_lower_.push_back(-INF); 
            model_.lp_.col_upper_.push_back(INF);
            model_.lp_.integrality_.push_back(HighsVarType::kContinuous);
            model_.lp_.num_col_++;
        }
    }


    auto lbs_comm = DataLoader::readVector(config_.inputDir + "/lower_upper_bounds/community_lower_bounds.txt");
    auto ubs_comm = DataLoader::readVector(config_.inputDir + "/lower_upper_bounds/community_upper_bounds.txt");

    for (size_t j = 0; j < lbs_comm.size(); ++j) {
        vars_.v_comm.push_back(model_.lp_.num_col_);
        model_.lp_.col_cost_.push_back(0.0);
        model_.lp_.col_lower_.push_back(lbs_comm[j]);
        model_.lp_.col_upper_.push_back(ubs_comm[j]);
        model_.lp_.integrality_.push_back(HighsVarType::kContinuous);
        model_.lp_.num_col_++;
    }
}

void MILPBuilder::addObjectiveLinearizationVariable() {
    vars_.w_linearization = model_.lp_.num_col_;

    model_.lp_.col_cost_.push_back(0.5); 
    model_.lp_.col_lower_.push_back(0.0);
    model_.lp_.col_upper_.push_back(INF);
    model_.lp_.integrality_.push_back(HighsVarType::kContinuous);
    model_.lp_.num_col_++;
}

// CONSTRAINTS

void MILPBuilder::addRow(double lb, double ub, const std::vector<int>& idxs, const std::vector<double>& vals) {
    model_.lp_.row_lower_.push_back(lb);
    model_.lp_.row_upper_.push_back(ub);
    
    for (size_t i = 0; i < idxs.size(); ++i) {

        if (std::abs(vals[i]) > 1e-12) { 
            model_.lp_.a_matrix_.index_.push_back(idxs[i]);
            model_.lp_.a_matrix_.value_.push_back(vals[i]);
        }
    }
    model_.lp_.a_matrix_.start_.push_back(model_.lp_.a_matrix_.index_.size());
    model_.lp_.num_row_++;
}

void MILPBuilder::addCommunityMassBalance() {
    std::vector<int> sp_col_offsets(data_.numSpecies + 1, 0);
    int total_sp_cols = 0;
    for (int k = 0; k < data_.numSpecies; ++k) {
        sp_col_offsets[k] = total_sp_cols;
        total_sp_cols += vars_.v[k].size();
    }
    sp_col_offsets[data_.numSpecies] = total_sp_cols;

    SparseMatrix mat = DataLoader::readSparseMatrix(config_.inputDir + "/community_data/community_stoichiometric_matrix.csv");

    std::map<int, std::vector<std::pair<int, double>>> rows;
    for (size_t i = 0; i < mat.values.size(); ++i) {
        rows[mat.rows[i]].push_back({mat.cols[i], mat.values[i]});
    }

    for (auto const& [r_idx, entries] : rows) {
        std::vector<int> idxs;
        std::vector<double> vals;
        
        for (auto const& entry : entries) {
            int csv_col = entry.first;
            double val = entry.second;
            int highs_var = -1;

            if (csv_col < total_sp_cols) {

                auto it = std::upper_bound(sp_col_offsets.begin(), sp_col_offsets.end(), csv_col);
                int k = std::distance(sp_col_offsets.begin(), it) - 1;
                
                int local_col = csv_col - sp_col_offsets[k];
                if (k >= 0 && k < data_.numSpecies && local_col < (int)vars_.v[k].size()) {
                    highs_var = vars_.v[k][local_col];
                }
            } else {
                int comm_local = csv_col - total_sp_cols;
                if (comm_local < (int)vars_.v_comm.size()) {
                    highs_var = vars_.v_comm[comm_local];
                }
            }

            if (highs_var != -1) {
                idxs.push_back(highs_var);
                vals.push_back(val);
            }
        }
        
        if (!idxs.empty()) {
            addRow(0.0, 0.0, idxs, vals);
        }
    }
}

void MILPBuilder::addCouplingConstraints() {

    for (int k = 0; k < data_.numSpecies; ++k) {
        std::stringstream ss_lb;
        ss_lb << "lower_upper_bounds/org" << (k + 1) << "_lower_bounds.txt";
        auto lbs = DataLoader::readVector(config_.inputDir + "/" + ss_lb.str());

        for (size_t j = 0; j < lbs.size(); ++j) {
            int x_idx = vars_.x[k];
            int v_idx = vars_.v[k][j];
            double lb_val = lbs[j];
            

            
            std::vector<int> idxs;
            std::vector<double> vals;


            if (std::abs(lb_val) > config_.tolerance) {
                idxs.push_back(x_idx);
                vals.push_back(lb_val);
            }
            
            idxs.push_back(v_idx);
            vals.push_back(-1.0);
            
            addRow(-INF, 0.0, idxs, vals);
        }
    }

    for (int k = 0; k < data_.numSpecies; ++k) {
        std::stringstream ss_ub;
        ss_ub << "lower_upper_bounds/org" << (k + 1) << "_upper_bounds.txt";
        auto ubs = DataLoader::readVector(config_.inputDir + "/" + ss_ub.str());

        for (size_t j = 0; j < ubs.size(); ++j) {
            int x_idx = vars_.x[k];
            int v_idx = vars_.v[k][j];
            double ub_val = ubs[j];
            
            
            std::vector<int> idxs;
            std::vector<double> vals;
            
            if (std::abs(ub_val) > config_.tolerance) {
                idxs.push_back(x_idx);
                vals.push_back(ub_val);
            }

            idxs.push_back(v_idx);
            vals.push_back(-1.0);
            
            addRow(0.0, INF, idxs, vals);
        }
    }
}

void MILPBuilder::addInternalMassBalance() {
    for (int k = 0; k < data_.numSpecies; ++k) {
        std::stringstream ss_S;
        ss_S << "per_org/org" << (k + 1) << "_stoichiometric_matrix.csv";
        
        SparseMatrix mat = DataLoader::readSparseMatrix(config_.inputDir + "/" + ss_S.str());

        std::map<int, std::vector<std::pair<int, double>>> rows;
        for (size_t i = 0; i < mat.values.size(); ++i) {
            rows[mat.rows[i]].push_back({mat.cols[i], mat.values[i]});
        }

        for (auto const& [r_idx, entries] : rows) {
            std::vector<int> idxs;
            std::vector<double> vals;
            for (auto const& entry : entries) {
                int col_local = entry.first;
                double val = entry.second;
                
                if (col_local < (int)vars_.v[k].size()) {
                    idxs.push_back(vars_.v[k][col_local]);
                    vals.push_back(val);
                }
            }
            if (!idxs.empty()) {
                addRow(0.0, 0.0, idxs, vals);
            }
        }
    }
}

void MILPBuilder::addGrowthConstraint() {
    if (std::isnan(data_.refGrowthMax)) return;

    std::vector<int> idxs;
    std::vector<double> vals;
    
    for (int k = 0; k < data_.numSpecies; ++k) {
        int bio_rxn_local_idx = data_.biomassIndices[k] - 1;
        if (bio_rxn_local_idx >= 0 && bio_rxn_local_idx < (int)vars_.v[k].size()) {
            idxs.push_back(vars_.v[k][bio_rxn_local_idx]);
            vals.push_back(1.0);
        }
    }
    double min_growth = config_.minCommunityGrowth * data_.refGrowthMax;
    addRow(min_growth, INF, idxs, vals);
}

void MILPBuilder::addFunctionConstraint() {
    if (data_.scfaIndices.empty() || std::isnan(data_.refScfaMax)) return; 

    std::vector<int> idxs;
    std::vector<double> vals;
    
    int total_species_cols = 0;
    for (const auto& v_k : vars_.v) total_species_cols += v_k.size();

    for (int global_idx : data_.scfaIndices) {

        int comm_local_idx = (global_idx - 1) - total_species_cols; 
        
        if (comm_local_idx >= 0 && comm_local_idx < (int)vars_.v_comm.size()) {
            idxs.push_back(vars_.v_comm[comm_local_idx]);
            vals.push_back(1.0);
        }
    }
    double min_prod = config_.reactionProductionFloor * data_.refScfaMax;
    addRow(min_prod, INF, idxs, vals);
}

void MILPBuilder::addMinSpeciesConstraint() {
    std::vector<int> idxs = vars_.x;
    std::vector<double> vals(vars_.x.size(), 1.0);
    addRow((double)config_.minSpeciesCount, INF, idxs, vals);
}

void MILPBuilder::addObjectiveConstraints() {
    for (int k = 0; k < data_.numSpecies; ++k) {
        int bio_idx = data_.biomassIndices[k] - 1; 
        
        
        std::stringstream ss_ub;
        ss_ub << "lower_upper_bounds/org" << (k + 1) << "_upper_bounds.txt";
        auto ubs = DataLoader::readVector(config_.inputDir + "/" + ss_ub.str());
        double ub_val = ubs[bio_idx];
        
        double weight = data_.weights[k];
        double coeff = 0.0;

        /* LEGACY ()
           w >= (weight / (UB+1)) * v
        
        coeff = -1.0 * (weight / (ub_val + 1.0));
        */

        /* PAPER
          	u >= v / ((UB+1) * weight)
         		1.0 * u - [1 / ((UB+1)*weight)] * v >= 0
        */
        
        double denominator = (ub_val + 1.0) * weight;


        if (std::abs(denominator) < 1e-9) {
            denominator = 1e-9; 
        }

        coeff = -1.0 * (1.0 / denominator);

        addRow(0.0, INF, {vars_.w_linearization, vars_.v[k][bio_idx]}, {1.0, coeff});
    }
}
