#pragma once
#include <string>
#include <vector>
#include <map>

struct SparseMatrix {
    std::vector<int> rows;
    std::vector<int> cols;
    std::vector<double> values;
    int n_rows = 0;
    int n_cols = 0;
};

struct SolverConfig {
    std::string inputDir;
    std::string outputFile; 
    
    double minCommunityGrowth = 0.8;
    double reactionProductionFloor = 0.8;
    int minSpeciesCount = 1;
    double timeLimit = 3600.0;
    double tolerance = 1e-9;
};

struct ProblemData {
    int numSpecies;
    
    std::vector<int> biomassIndices;
    std::vector<int> scfaIndices;
    std::vector<double> weights;
    
    double refGrowthMax;
    double refScfaMax;
    
    std::map<int, std::string> speciesMap;
    std::map<std::string, std::string> commFluxMap;
    std::map<std::string, double> refScfaBreakdown;

    std::vector<std::vector<std::string>> speciesRxnNames;
};
